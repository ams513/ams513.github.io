// Stark World Engine Runtime - enemies (see StarkEnemy.h).
// AAIController::RunBehaviorTree: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/AIModule/AAIController/RunBehaviorTree
// APawn::AddMovementInput: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/GameFramework/APawn/AddMovementInput
// UWorld::LineTraceSingleByChannel: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/Engine/UWorld/LineTraceSingleByChannel
#include "StarkEnemy.h"
#include "StarkGameSubsystem.h"
#include "StarkRules.h"
#include "StarkCharacter.h"
#include "StarkWorldActors.h"
#include "BehaviorTree/BehaviorTree.h"
#include "Components/CapsuleComponent.h"
#include "Components/ChildActorComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/GameInstance.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "UObject/ConstructorHelpers.h"

static UStarkGameSubsystem* StarkSubE(const UObject* Ctx)
{
	const UWorld* W = Ctx ? Ctx->GetWorld() : nullptr;
	UGameInstance* GI = W ? W->GetGameInstance() : nullptr;
	return GI ? GI->GetSubsystem<UStarkGameSubsystem>() : nullptr;
}

AStarkEnemyCharacter::AStarkEnemyCharacter()
{
	PrimaryActorTick.bCanEverTick = true;
	AIControllerClass = AStarkEnemyAIController::StaticClass();
	AutoPossessAI = EAutoPossessAI::PlacedInWorldOrSpawned;
	bUseControllerRotationYaw = false;
	GetCharacterMovement()->bOrientRotationToMovement = true;
	GetCharacterMovement()->RotationRate = FRotator(0.f, 540.f, 0.f);
	GetCharacterMovement()->GravityScale = 2400.f / 980.f;
	GetCapsuleComponent()->InitCapsuleSize(45.f, 60.f);
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Sphere(TEXT("/Engine/BasicShapes/Sphere.Sphere"));
	BodyMesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("BodyMesh"));
	BodyMesh->SetupAttachment(RootComponent);
	BodyMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	if (Sphere.Succeeded()) { BodyMesh->SetStaticMesh(Sphere.Object); }
	Visual = CreateDefaultSubobject<UChildActorComponent>(TEXT("Visual"));
	Visual->SetupAttachment(RootComponent);
}

bool AStarkEnemyCharacter::IsProtected() const
{
	UStarkGameSubsystem* G = StarkSubE(this);
	return (!Age.IsEmpty() && Age != TEXT("adult")) || (G && G->Rules && G->Rules->IsMinor(EnemyId));
}

bool AStarkEnemyCharacter::IsBoss() const { return Def.Boss || Kind == TEXT("boss"); }
FString AStarkEnemyCharacter::Title() const { return DisplayName.IsEmpty() ? Def.Name : DisplayName; }

FString AStarkEnemyCharacter::GetGoneKey() const
{
	if (!GoneKeyOverride.IsEmpty()) { return GoneKeyOverride; }
	UStarkGameSubsystem* G = StarkSubE(this);
	return (G && ObjectIndex >= 0) ? G->GoneKey(ObjectIndex) : FString();
}

void AStarkEnemyCharacter::BeginPlay()
{
	Super::BeginPlay();
	UStarkGameSubsystem* G = StarkSubE(this);
	if (G && G->IsGone(GetGoneKey())) { Destroy(); return; }
	if (IsProtected())
	{
		// child-safety backstop: a child or teen can never be an enemy (the exporter refuses such worlds)
		UE_LOG(LogTemp, Warning, TEXT("[Stark World Engine] child-safety: %s is a minor and cannot be an enemy; removed"), *GetName());
		Destroy();
		return;
	}
	if (G && G->Rules)
	{
		if (const FStarkEnemyDef* D = G->Rules->FindEnemy(Kind)) { Def = *D; }
		const float Base = HpOverride > 0 ? (float)HpOverride : (float)Def.Hp;
		MaxHp = FMath::Max(1.f, (float)FMath::RoundToInt(Base * G->Rules->HpMul() * (bSideView && IsBoss() ? 0.6f : 1.f)));
		G->RegisterEnemy(this);
	}
	Hp = MaxHp;
	Home = GetActorLocation();
	WanderTarget = Home;
	ShotT = 1.f + FMath::FRand();
	const float S = SizeScale * (IsBoss() ? 1.8f : 1.f);
	SetActorScale3D(FVector(S));
	UCharacterMovementComponent* M = GetCharacterMovement();
	M->MaxWalkSpeed = Def.Speed * 100.f * (bSideView ? 1.45f : 1.f);
	if (Def.Fly && !bSideView) { M->SetMovementMode(MOVE_Flying); M->BrakingDecelerationFlying = 2000.f; }
	if (bSideView)
	{
		M->SetPlaneConstraintEnabled(true);
		M->SetPlaneConstraintNormal(FVector(0.f, 1.f, 0.f));
		M->GravityScale = (1500.f * 6.25f) / 980.f;
	}
	if (VisualClass) { Visual->SetChildActorClass(VisualClass); BodyMesh->SetVisibility(false); }
	else if (UMaterialInterface* Base = BodyMesh->GetMaterial(0))
	{
		if (UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Base, this))
		{
			Mid->SetVectorParameterValue(TEXT("Color"), Def.Color);
			BodyMesh->SetMaterial(0, Mid);
		}
	}
}

void AStarkEnemyCharacter::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	if (UStarkGameSubsystem* G = StarkSubE(this)) { G->UnregisterEnemy(this); }
	Super::EndPlay(EndPlayReason);
}

void AStarkEnemyCharacter::TakeHit(float Damage, FVector Direction)
{
	UStarkGameSubsystem* G = StarkSubE(this);
	if (bDead || !G || !G->Rules || IsProtected()) { return; }
	const bool bCrit = FMath::FRand() < G->Rules->Def.Rules.CritChance;
	Hp -= Damage * (bCrit ? 2.f : 1.f);
	HitT = 0.22f;
	if (!IsBoss() && !bSideView)
	{
		const FVector Knock = GetActorLocation() + FVector(Direction.X, Direction.Y, 0.f).GetSafeNormal() * 120.f;
		const FVector2D P = UEToStarkXZ(Knock);
		if (G->WaterDepthAt(P.X, P.Y) <= 1.3f) { SetActorLocation(Knock, true); }
	}
	State = TEXT("chase");
	G->PlaySfx(TEXT("hit"));
	if (bCrit) { G->Rules->Toast(TEXT("Critical hit!")); }
	if (Hp <= 0.f) { Die(); }
	G->Changed();
}

void AStarkEnemyCharacter::Die()
{
	UStarkGameSubsystem* G = StarkSubE(this);
	if (bDead) { return; }
	bDead = true;
	Hp = 0.f;
	if (G && G->Rules)
	{
		G->MarkGone(GetGoneKey());
		G->Rules->Score += 50;
		G->PlaySfx(TEXT("boom"));
		G->Rules->AddXp(Def.Xp);
		G->Rules->Gold += Def.Gold;
		FStarkEvent E;
		E.Kind = Kind;
		E.Id = bSideView ? FString() : EnemyId;
		G->Rules->Event(TEXT("defeat"), E);
		if (!bSideView && FMath::FRand() < (IsBoss() ? 1.f : 0.18f))
		{
			const FTransform Xf(FRotator::ZeroRotator, GetActorLocation());
			if (AStarkInteractable* Drop = GetWorld()->SpawnActorDeferred<AStarkInteractable>(AStarkInteractable::StaticClass(), Xf))
			{
				Drop->Kind = EStarkThing::Item;
				Drop->Item = IsBoss() ? TEXT("elixir") : TEXT("potion");
				Drop->FinishSpawning(Xf);
			}
		}
		G->UnregisterEnemy(this);
		G->Changed();
	}
	Destroy();
}

// ---------------------------------------------------------------- AI controller
AStarkEnemyAIController::AStarkEnemyAIController()
{
	PrimaryActorTick.bCanEverTick = true;
}

void AStarkEnemyAIController::OnPossess(APawn* InPawn)
{
	Super::OnPossess(InPawn);
	bUsingTree = BehaviorTreeAsset != nullptr && RunBehaviorTree(BehaviorTreeAsset);
}

void AStarkEnemyAIController::Shoot(AStarkEnemyCharacter* E, const FVector& Velocity, float Damage, const FLinearColor& Color)
{
	const FTransform Xf(FRotator::ZeroRotator, E->GetActorLocation() + FVector(0.f, 0.f, 60.f));
	if (AStarkProjectile* Pr = GetWorld()->SpawnActorDeferred<AStarkProjectile>(AStarkProjectile::StaticClass(), Xf))
	{
		Pr->Velocity = Velocity;
		Pr->Damage = Damage;
		Pr->bFromEnemy = true;
		Pr->Color = Color;
		Pr->FinishSpawning(Xf);
	}
}

void AStarkEnemyAIController::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	AStarkEnemyCharacter* E = Cast<AStarkEnemyCharacter>(GetPawn());
	UStarkGameSubsystem* G = StarkSubE(this);
	if (!E || E->bDead || bUsingTree || !G || G->IsBusy()) { return; }
	E->AliveT += DeltaSeconds;
	E->HitT = FMath::Max(0.f, E->HitT - DeltaSeconds);
	E->Cooldown = FMath::Max(0.f, E->Cooldown - DeltaSeconds);
	if (E->bSideView) { Think2D(E, DeltaSeconds); } else { Think3D(E, DeltaSeconds); }
}

void AStarkEnemyAIController::Think3D(AStarkEnemyCharacter* E, float Dt)
{
	UStarkGameSubsystem* G = StarkSubE(this);
	AStarkPlayerCharacter* Pl = G ? G->GetPlayer() : nullptr;
	if (!Pl) { return; }
	const FStarkEnemyDef& D = E->Def;
	FVector To = Pl->GetActorLocation() - E->GetActorLocation();
	To.Z = 0.f;
	const float Dist = To.Size() / 100.f;                       // metres, like the browser engine
	const FVector Dir = To.GetSafeNormal();
	const float HomeDist = FVector::Dist2D(E->GetActorLocation(), E->Home) / 100.f;
	const float Sight = D.Sight;
	const float S = E->SizeScale;
	E->GetCharacterMovement()->MaxWalkSpeed = D.Speed * 100.f * (E->bEnraged ? 1.35f : 1.f);
	if (Dist > 80.f && E->State == TEXT("patrol")) { return; }
	if (E->State != TEXT("chase") && Dist < Sight && HomeDist < 26.f) { E->State = TEXT("chase"); }
	if (E->State == TEXT("chase") && (Dist > Sight * 1.7f || HomeDist > 30.f)) { E->State = TEXT("return"); }
	FVector Move = FVector::ZeroVector;
	float SpeedMul = 1.f;
	if (E->State == TEXT("return"))
	{
		Move = (E->Home - E->GetActorLocation()).GetSafeNormal2D();
		if (HomeDist < 1.f) { E->State = TEXT("patrol"); }
	}
	else if (E->State == TEXT("patrol"))
	{
		E->WanderT -= Dt;
		if (E->WanderT <= 0.f)
		{
			E->WanderT = 2.f + FMath::FRand() * 3.f;
			const float A = FMath::FRand() * 2.f * PI;
			const float R = FMath::FRand() * E->Patrol * 100.f;
			E->WanderTarget = E->Home + FVector(FMath::Cos(A) * R, FMath::Sin(A) * R, 0.f);
		}
		const FVector Pd = E->WanderTarget - E->GetActorLocation();
		if (Pd.Size2D() > 40.f) { Move = Pd.GetSafeNormal2D(); SpeedMul = 0.45f; }
	}
	else if (E->HitT <= 0.f)
	{
		if (D.Ranged)
		{
			if (Dist < 6.f) { Move = -Dir; } else if (Dist > 11.f) { Move = Dir; }
			E->ShotT -= Dt;
			if (E->ShotT <= 0.f && Dist < 16.f) { E->ShotT = 1.9f; Shoot(E, Dir * 1100.f, (float)D.Dmg, FLinearColor(0.6f, 1.f, 0.4f)); G->PlaySfx(TEXT("laser")); }
		}
		else if (E->WindUp > 0.f)
		{
			E->WindUp -= Dt;
			if (E->WindUp <= 0.f) { if (Dist < 2.6f + S) { Pl->HurtPlayer((float)D.Dmg); } E->Cooldown = 1.6f; }
		}
		else
		{
			const float Reach = 1.1f + (E->IsBoss() ? 1.4f * S : (D.Fly ? 0.2f : 0.3f * S));
			if (Dist > Reach * 0.9f) { Move = Dir; }
			if (Dist < Reach && E->Cooldown <= 0.f)
			{
				if (E->Kind == TEXT("brute") || E->IsBoss()) { E->WindUp = 0.55f; }
				else { E->Cooldown = 1.2f; Pl->HurtPlayer((float)D.Dmg); }
			}
		}
		if (E->IsBoss())
		{
			E->VolleyT -= Dt;
			if (E->VolleyT <= 0.f)
			{
				E->VolleyT = E->bEnraged ? 3.2f : 5.f;
				for (int32 B = 0; B < 14; ++B)
				{
					const float Ba = B / 14.f * 2.f * PI;
					Shoot(E, FVector(FMath::Cos(Ba), FMath::Sin(Ba), 0.f) * 800.f, (float)D.Dmg, FLinearColor(1.f, 0.35f, 0.8f));
				}
				G->PlaySfx(TEXT("boom"));
			}
			if (!E->bEnraged && E->Hp < E->MaxHp * 0.5f)
			{
				E->bEnraged = true;
				G->Rules->Toast(E->Title() + TEXT(" is enraged!"), TEXT("q"));
				for (int32 Sm = 0; Sm < 2; ++Sm)
				{
					const FTransform Xf(FRotator::ZeroRotator, E->GetActorLocation() + FVector(Sm ? 300.f : -300.f, 200.f, 50.f));
					if (AStarkEnemyCharacter* Add = GetWorld()->SpawnActorDeferred<AStarkEnemyCharacter>(AStarkEnemyCharacter::StaticClass(), Xf,
						nullptr, nullptr, ESpawnActorCollisionHandlingMethod::AdjustIfPossibleButAlwaysSpawn))
					{
						Add->Kind = TEXT("grunt");
						Add->Patrol = 4.f;
						Add->FinishSpawning(Xf);
					}
				}
			}
		}
	}
	if (!Move.IsNearlyZero())
	{
		const FVector2D Next = UEToStarkXZ(E->GetActorLocation() + Move * 100.f);
		const FStarkLevelDef L = G->GetLevelDef(G->GetLevelIndex());
		const bool bDeep = G->WaterDepthAt(Next.X, Next.Y) > 1.3f;
		const bool bOut = FMath::Abs(Next.X) > L.Size - 1.f || FMath::Abs(Next.Y) > L.Size - 1.f;
		if (!bDeep && !bOut) { E->AddMovementInput(Move, SpeedMul); }
	}
	if (D.Fly)
	{
		const FVector2D P = UEToStarkXZ(E->GetActorLocation());
		const float Want = (G->TerrainHeightAt(P.X, P.Y) + 1.2f + FMath::Sin(E->AliveT * 2.f + E->Home.X) * 0.4f) * 100.f;
		FVector Loc = E->GetActorLocation();
		Loc.Z = FMath::FInterpTo(Loc.Z, Want + E->GetCapsuleComponent()->GetScaledCapsuleHalfHeight(), Dt, 6.f);
		E->SetActorLocation(Loc);
	}
}

void AStarkEnemyAIController::Think2D(AStarkEnemyCharacter* E, float Dt)
{
	// the browser platformer: walk, turn at walls and ledges, archers / bosses shoot, stomp from above hurts them
	UStarkGameSubsystem* G = StarkSubE(this);
	AStarkPlayerCharacter* Pl = G ? G->GetPlayer() : nullptr;
	if (!Pl) { return; }
	const FVector Me = E->GetActorLocation();
	const FVector Hero = Pl->GetActorLocation();
	if (E->IsBoss()) { E->SideDir = Hero.X > Me.X ? 1.f : -1.f; }
	FHitResult Hit;
	FCollisionQueryParams Q(SCENE_QUERY_STAT(StarkEnemy2D), false, E);
	const FVector Ahead = Me + FVector(E->SideDir * 80.f * E->SizeScale, 0.f, 0.f);
	const bool bWall = GetWorld()->LineTraceSingleByChannel(Hit, Me, Ahead, ECC_WorldStatic, Q);
	const bool bFloor = GetWorld()->LineTraceSingleByChannel(Hit, Ahead, Ahead - FVector(0.f, 0.f, 250.f), ECC_WorldStatic, Q);
	if (bWall || !bFloor) { E->SideDir = -E->SideDir; }
	E->AddMovementInput(FVector(E->SideDir, 0.f, 0.f), 1.f);
	if (E->Kind == TEXT("archer") || E->IsBoss())
	{
		E->ShotT -= Dt;
		const FVector D = Hero - Me;
		if (E->ShotT <= 0.f && D.Size() < 420.f * 6.25f)
		{
			E->ShotT = E->IsBoss() ? 1.3f : 2.2f;
			const int32 N = E->IsBoss() ? 5 : 1;
			const float Base = FMath::Atan2(D.Z, D.X);
			for (int32 i = 0; i < N; ++i)
			{
				const float A = Base + (i - (N - 1) / 2.f) * 0.25f;
				Shoot(E, FVector(FMath::Cos(A), 0.f, FMath::Sin(A)) * 260.f * 6.25f, 1.f,
					E->IsBoss() ? FLinearColor(1.f, 0.35f, 0.8f) : FLinearColor(0.6f, 1.f, 0.4f));
			}
			G->PlaySfx(TEXT("laser"));
		}
	}
	const float R = E->GetCapsuleComponent()->GetScaledCapsuleRadius() + 60.f;
	const float HalfH = E->GetCapsuleComponent()->GetScaledCapsuleHalfHeight();
	if (FMath::Abs(Hero.X - Me.X) < R && FMath::Abs(Hero.Z - Me.Z) < HalfH + 100.f)
	{
		const bool bStomp = Pl->GetVelocity().Z < 0.f && Hero.Z > Me.Z + HalfH * 0.5f;
		if (bStomp)
		{
			Pl->LaunchCharacter(FVector(0.f, 0.f, 420.f * 6.25f), false, true);
			E->TakeHit(E->IsBoss() ? 3.f : 99.f, FVector::UpVector);
		}
		else if (E->Cooldown <= 0.f)
		{
			E->Cooldown = 0.8f;
			Pl->HurtPlayer((float)E->Def.Dmg);
		}
	}
}
