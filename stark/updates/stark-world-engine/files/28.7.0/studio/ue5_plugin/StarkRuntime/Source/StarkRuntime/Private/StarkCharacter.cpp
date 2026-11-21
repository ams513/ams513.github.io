// Stark World Engine Runtime - the hero (see StarkCharacter.h).
// UCharacterMovementComponent: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/GameFramework/UCharacterMovementComponent
// Plane constraint (2.5D): https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/GameFramework/UMovementComponent/SetPlaneConstraintNormal
// APlayerController::GetInputMouseDelta: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/GameFramework/APlayerController/GetInputMouseDelta
// ConstructorHelpers: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/CoreUObject/UObject/ConstructorHelpers
#include "StarkCharacter.h"
#include "StarkGameSubsystem.h"
#include "StarkRules.h"
#include "StarkEnemy.h"
#include "StarkNpc.h"
#include "StarkWorldActors.h"
#include "Camera/CameraComponent.h"
#include "Components/CapsuleComponent.h"
#include "Components/ChildActorComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/GameInstance.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/SpringArmComponent.h"
#include "InputCoreTypes.h"
#include "UObject/ConstructorHelpers.h"

static UStarkGameSubsystem* StarkSub(const UObject* Ctx)
{
	const UWorld* W = Ctx ? Ctx->GetWorld() : nullptr;
	UGameInstance* GI = W ? W->GetGameInstance() : nullptr;
	return GI ? GI->GetSubsystem<UStarkGameSubsystem>() : nullptr;
}

AStarkPlayerCharacter::AStarkPlayerCharacter()
{
	PrimaryActorTick.bCanEverTick = true;
	GetCapsuleComponent()->InitCapsuleSize(40.f, 90.f);
	bUseControllerRotationYaw = false;
	bUseControllerRotationPitch = false;
	bUseControllerRotationRoll = false;
	UCharacterMovementComponent* M = GetCharacterMovement();
	M->bOrientRotationToMovement = true;
	M->RotationRate = FRotator(0.f, 720.f, 0.f);
	M->MaxWalkSpeed = 700.f;                 // browser: 7 m/s
	M->JumpZVelocity = 850.f;                // browser: 8.5 m/s
	M->GravityScale = 2400.f / 980.f;        // browser: 24 m/s^2
	M->AirControl = 0.6f;
	M->MaxStepHeight = 60.f;
	M->SetWalkableFloorAngle(50.f);

	CameraBoom = CreateDefaultSubobject<USpringArmComponent>(TEXT("CameraBoom"));
	CameraBoom->SetupAttachment(RootComponent);
	CameraBoom->TargetArmLength = 850.f;
	CameraBoom->bUsePawnControlRotation = true;
	CameraBoom->SocketOffset = FVector(0.f, 0.f, 60.f);
	FollowCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("FollowCamera"));
	FollowCamera->SetupAttachment(CameraBoom, USpringArmComponent::SocketName);
	FollowCamera->bUsePawnControlRotation = false;
	FollowCamera->SetFieldOfView(65.f);

	static ConstructorHelpers::FObjectFinder<UStaticMesh> Cyl(TEXT("/Engine/BasicShapes/Cylinder.Cylinder"));
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Sphere(TEXT("/Engine/BasicShapes/Sphere.Sphere"));
	BodyMesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("BodyMesh"));
	BodyMesh->SetupAttachment(RootComponent);
	BodyMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	BodyMesh->SetRelativeLocation(FVector(0.f, 0.f, -20.f));
	BodyMesh->SetRelativeScale3D(FVector(0.7f, 0.7f, 1.2f));
	HeadMesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("HeadMesh"));
	HeadMesh->SetupAttachment(RootComponent);
	HeadMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	HeadMesh->SetRelativeLocation(FVector(0.f, 0.f, 75.f));
	HeadMesh->SetRelativeScale3D(FVector(0.55f));
	if (Cyl.Succeeded()) { BodyMesh->SetStaticMesh(Cyl.Object); }
	if (Sphere.Succeeded()) { HeadMesh->SetStaticMesh(Sphere.Object); }
	Visual = CreateDefaultSubobject<UChildActorComponent>(TEXT("Visual"));
	Visual->SetupAttachment(RootComponent);
	Visual->SetRelativeLocation(FVector(0.f, 0.f, -90.f));
}

void AStarkPlayerCharacter::BeginPlay()
{
	Super::BeginPlay();
	SpawnLocation = GetActorLocation();
	if (VisualClass)
	{
		Visual->SetChildActorClass(VisualClass);
		BodyMesh->SetVisibility(false);
		HeadMesh->SetVisibility(false);
	}
	UStarkGameSubsystem* G = StarkSub(this);
	bSideView = G && G->IsSideView();
	if (bSideView)
	{
		// 2.5D chapter: 1 browser tile (32 px) = 2 m; the browser's px/s numbers scaled by 6.25 cm/px
		UCharacterMovementComponent* M = GetCharacterMovement();
		M->SetPlaneConstraintEnabled(true);
		M->SetPlaneConstraintNormal(FVector(0.f, 1.f, 0.f));
		M->MaxWalkSpeed = 230.f * 6.25f;
		M->JumpZVelocity = 570.f * 6.25f;
		M->GravityScale = (1500.f * 6.25f) / 980.f;
		M->AirControl = 1.f;
		CameraBoom->bUsePawnControlRotation = false;
		CameraBoom->SetUsingAbsoluteRotation(true);
		CameraBoom->SetWorldRotation(FRotator(-8.f, 90.f, 0.f));
		CameraBoom->TargetArmLength = 1600.f;
	}
	else if (APlayerController* PC = Cast<APlayerController>(GetController()))
	{
		PC->SetControlRotation(FRotator(-24.f, GetActorRotation().Yaw, 0.f));
	}
}

FVector AStarkPlayerCharacter::FacingVector() const
{
	return GetActorForwardVector().GetSafeNormal2D();
}

FVector2D AStarkPlayerCharacter::GetPlanXZ() const
{
	const FVector L = GetActorLocation();
	return bSideView ? FVector2D(L.X / 100.f, L.Z / 100.f) : UEToStarkXZ(L);
}

void AStarkPlayerCharacter::TeleportToPlan(float PlanX, float PlanZ)
{
	UStarkGameSubsystem* G = StarkSub(this);
	FVector Loc;
	if (bSideView)
	{
		Loc = FVector(PlanX * 100.f, 0.f, PlanZ * 100.f + 20.f);
	}
	else
	{
		const float H = G ? G->TerrainHeightAt(PlanX, PlanZ) : 0.f;
		Loc = StarkToUE(PlanX, H, PlanZ) + FVector(0.f, 0.f, GetCapsuleComponent()->GetScaledCapsuleHalfHeight() + 20.f);
	}
	SetActorLocation(Loc, false, nullptr, ETeleportType::TeleportPhysics);
	GetCharacterMovement()->StopMovementImmediately();
}

void AStarkPlayerCharacter::Respawn(bool bAtPoint, FVector2D PlanXZ)
{
	if (bAtPoint) { TeleportToPlan(PlanXZ.X, PlanXZ.Y); }
	else
	{
		SetActorLocation(SpawnLocation, false, nullptr, ETeleportType::TeleportPhysics);
		GetCharacterMovement()->StopMovementImmediately();
	}
	InvT = 2.f;
}

void AStarkPlayerCharacter::HurtPlayer(float Damage)
{
	if (InvT > 0.f || DashT > 0.f) { return; }
	InvT = 1.f;
	if (UStarkGameSubsystem* G = StarkSub(this)) { G->OnPlayerHit(Damage); }
}

AActor* AStarkPlayerCharacter::NearestInteractable(FString& OutPrompt) const
{
	UStarkGameSubsystem* G = StarkSub(this);
	OutPrompt.Reset();
	if (!G || !G->Rules) { return nullptr; }
	const float Radius = G->Rules->Def.Rules.InteractRadius * 100.f * (bSideView ? 0.6f : 1.f);
	AActor* Best = nullptr;
	float BestD = Radius;
	const FVector Me = GetActorLocation();
	for (UStarkNpcComponent* N : G->Npcs())
	{
		const float D = FVector::Dist2D(N->GetOwner()->GetActorLocation(), Me);
		if (D < BestD) { BestD = D; Best = N->GetOwner(); OutPrompt = TEXT("Talk to ") + N->DisplayName; }
	}
	for (AStarkInteractable* T : G->Interactables())
	{
		if (!T->CanInteract()) { continue; }
		const float Extra = T->Kind == EStarkThing::Door ? 60.f : 0.f;
		const float D = FVector::Dist2D(T->GetActorLocation(), Me);
		if (D < BestD + Extra) { BestD = D; Best = T; OutPrompt = T->PromptText(); }
	}
	return Best;
}

void AStarkPlayerCharacter::Interact()
{
	UStarkGameSubsystem* G = StarkSub(this);
	if (!G || G->IsBusy()) { return; }
	FString Prompt;
	AActor* Target = NearestInteractable(Prompt);
	if (!Target) { return; }
	if (UStarkNpcComponent* N = Target->FindComponentByClass<UStarkNpcComponent>()) { N->Interact(this); return; }
	if (AStarkInteractable* T = Cast<AStarkInteractable>(Target)) { T->Interact(this); }
}

void AStarkPlayerCharacter::Attack()
{
	UStarkGameSubsystem* G = StarkSub(this);
	if (!G || AttackT > 0.f || G->IsBusy()) { return; }
	AttackT = 0.28f;
	G->PlaySfx(TEXT("laser"));
	const FVector F = FacingVector();
	const float Atk = (float)G->GetStats().Atk;
	for (AStarkEnemyCharacter* E : G->Enemies())
	{
		FVector D = E->GetActorLocation() - GetActorLocation();
		if (bSideView)
		{
			if (FMath::Abs(D.Z) < 180.f && FMath::Abs(D.X) < 250.f && D.X * F.X >= -30.f) { E->TakeHit(Atk, D.GetSafeNormal()); }
			continue;
		}
		D.Z = 0.f;
		const float Dist = D.Size();
		const float Reach = 250.f + (E->IsBoss() ? 150.f * E->SizeScale : 0.f);
		if (Dist < Reach && FVector::DotProduct(D.GetSafeNormal(), F) > -0.25f) { E->TakeHit(Atk, D.GetSafeNormal()); }
	}
}

void AStarkPlayerCharacter::Whirl()
{
	UStarkGameSubsystem* G = StarkSub(this);
	if (!G || !G->Rules || !G->Rules->UseAbility(TEXT("Whirl"))) { return; }
	G->PlaySfx(TEXT("magic"));
	const float Dmg = FMath::CeilToFloat(G->GetStats().Atk * 1.5f);
	for (AStarkEnemyCharacter* E : G->Enemies())
	{
		const FVector D = E->GetActorLocation() - GetActorLocation();
		if (D.Size2D() < 360.f + (E->IsBoss() ? 200.f : 0.f)) { E->TakeHit(Dmg, D.GetSafeNormal2D()); }
	}
	G->Changed();
}

void AStarkPlayerCharacter::Bolt()
{
	UStarkGameSubsystem* G = StarkSub(this);
	if (!G || !G->Rules || !G->Rules->UseAbility(TEXT("Star Bolt"))) { return; }
	G->PlaySfx(TEXT("magic"));
	const FVector F = FacingVector();
	const FTransform Xf(FRotator::ZeroRotator, GetActorLocation() + F * 100.f + FVector(0.f, 0.f, 20.f));
	if (AStarkProjectile* Pr = GetWorld()->SpawnActorDeferred<AStarkProjectile>(AStarkProjectile::StaticClass(), Xf))
	{
		Pr->Velocity = F * 1800.f;
		Pr->Damage = (float)G->GetStats().Atk + 1.f;
		Pr->bFromEnemy = false;
		Pr->Life = 1.4f;
		Pr->Color = FLinearColor(0.6f, 0.9f, 1.f);
		Pr->FinishSpawning(Xf);
	}
	G->Changed();
}

void AStarkPlayerCharacter::Dash()
{
	UStarkGameSubsystem* G = StarkSub(this);
	if (!G || !G->Rules || !G->Rules->UseAbility(TEXT("Dash"))) { return; }
	DashT = 0.2f;
	G->PlaySfx(TEXT("jump"));
	LaunchCharacter(FacingVector() * (bSideView ? 620.f * 6.25f : 2400.f), true, false);
	G->Changed();
}

void AStarkPlayerCharacter::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (InvT > 0.f) { InvT -= DeltaSeconds; }
	if (DashT > 0.f) { DashT -= DeltaSeconds; }
	if (AttackT > 0.f) { AttackT -= DeltaSeconds; }
	HandleKeys(DeltaSeconds);
	UStarkGameSubsystem* G = StarkSub(this);
	if (!G) { return; }
	ReachT -= DeltaSeconds;
	if (ReachT <= 0.f && !bSideView)
	{
		ReachT = 0.25f;
		const FVector2D P = GetPlanXZ();
		FStarkEvent E;
		E.X = P.X;
		E.Z = P.Y;
		G->QuestEvent(TEXT("reach"), E);
	}
	if (GetActorLocation().Z < -5000.f) { HurtPlayer(1.f); Respawn(false, FVector2D::ZeroVector); }
	BodyMesh->SetVisibility(!VisualClass && !(InvT > 0.f && FMath::Fmod(InvT * 20.f, 2.f) < 1.f));
}

void AStarkPlayerCharacter::HandleKeys(float Dt)
{
	APlayerController* PC = Cast<APlayerController>(GetController());
	UStarkGameSubsystem* G = StarkSub(this);
	if (!PC || !G || !G->Rules) { return; }
	static const FKey Digits[9] = { EKeys::One, EKeys::Two, EKeys::Three, EKeys::Four, EKeys::Five, EKeys::Six,
		EKeys::Seven, EKeys::Eight, EKeys::Nine };
	auto Pressed = [PC](const FKey& K) { return PC->WasInputKeyJustPressed(K); };
	auto Down = [PC](const FKey& K) { return PC->IsInputKeyDown(K); };

	// dialogue: 1-9 pick, E / Enter / Space when there is one answer, Esc closes
	if (G->IsDialogueOpen())
	{
		for (int32 i = 0; i < 9; ++i) { if (Pressed(Digits[i])) { G->Choose(i); return; } }
		if ((Pressed(EKeys::E) || Pressed(EKeys::Enter) || Pressed(EKeys::SpaceBar)) && G->Rules->VisibleChoices.Num() == 1) { G->Choose(0); }
		if (Pressed(EKeys::Escape)) { G->CloseDialogue(); }
		return;
	}
	// menus: Esc / M menu (1-3 save, 4-6 load, 7 autosave), L quests, I bag (1-9 use)
	const FString Modal = G->GetModal();
	if (Pressed(EKeys::Escape) || Pressed(EKeys::M)) { G->SetModal(Modal.IsEmpty() ? TEXT("menu") : TEXT("")); return; }
	if (Pressed(EKeys::L)) { G->SetModal(Modal == TEXT("quests") ? TEXT("") : TEXT("quests")); return; }
	if (Pressed(EKeys::I) || Pressed(EKeys::Tab)) { G->SetModal(Modal == TEXT("bag") ? TEXT("") : TEXT("bag")); return; }
	if (Modal == TEXT("menu"))
	{
		for (int32 i = 0; i < 3; ++i)
		{
			if (Pressed(Digits[i])) { G->SaveToSlot(FString::FromInt(i + 1)); }
			if (Pressed(Digits[i + 3])) { G->LoadFromSlot(FString::FromInt(i + 1)); return; }
		}
		if (Pressed(Digits[6])) { G->LoadFromSlot(TEXT("auto")); }
		return;
	}
	if (Modal == TEXT("bag"))
	{
		TArray<FString> Ids;
		G->Rules->Inventory.GetKeys(Ids);
		for (int32 i = 0; i < 9 && i < Ids.Num(); ++i) { if (Pressed(Digits[i])) { G->UseItem(Ids[i]); } }
		return;
	}
	if (!Modal.IsEmpty() || G->IsBusy()) { return; }
	if (Pressed(EKeys::H)) { G->Quaff(); }

	// camera: Z / C or right mouse drag (3D)
	if (!bSideView)
	{
		FRotator R = PC->GetControlRotation();
		if (Down(EKeys::Z)) { R.Yaw += 120.f * Dt; }
		if (Down(EKeys::C)) { R.Yaw -= 120.f * Dt; }
		if (Down(EKeys::RightMouseButton))
		{
			float Dx = 0.f, Dy = 0.f;
			PC->GetInputMouseDelta(Dx, Dy);
			R.Yaw += Dx * 2.5f;
			R.Pitch = FMath::Clamp(FRotator::NormalizeAxis(R.Pitch + Dy * 2.5f), -70.f, 10.f);
		}
		PC->SetControlRotation(R);
	}
	// movement
	const float Fwd = (Down(EKeys::W) || Down(EKeys::Up) ? 1.f : 0.f) - (Down(EKeys::S) || Down(EKeys::Down) ? 1.f : 0.f);
	const float Side = (Down(EKeys::D) || Down(EKeys::Right) ? 1.f : 0.f) - (Down(EKeys::A) || Down(EKeys::Left) ? 1.f : 0.f);
	FVector Dir = FVector::ZeroVector;
	if (bSideView) { Dir = FVector(Side, 0.f, 0.f); }
	else
	{
		const FRotator Yaw(0.f, PC->GetControlRotation().Yaw, 0.f);
		Dir = FRotationMatrix(Yaw).GetUnitAxis(EAxis::X) * Fwd + FRotationMatrix(Yaw).GetUnitAxis(EAxis::Y) * Side;
	}
	if (!Dir.IsNearlyZero())
	{
		bool bBlocked = false;
		if (!bSideView)
		{
			// deep water and the play-area edge stop the hero (browser engine rules)
			const FVector2D Next = UEToStarkXZ(GetActorLocation() + Dir.GetSafeNormal() * 100.f);
			const FVector2D Now = GetPlanXZ();
			const FStarkLevelDef L = G->GetLevelDef(G->GetLevelIndex());
			if (G->WaterDepthAt(Next.X, Next.Y) > 1.3f && G->WaterDepthAt(Now.X, Now.Y) <= 1.3f) { bBlocked = true; }
			if (FMath::Abs(Next.X) > L.Size - 1.f || FMath::Abs(Next.Y) > L.Size - 1.f) { bBlocked = true; }
			const float Speed = G->GetStats().Speed * (G->WaterDepthAt(Now.X, Now.Y) > 0.15f ? 0.6f : 1.f);
			GetCharacterMovement()->MaxWalkSpeed = 700.f * Speed;
		}
		else
		{
			GetCharacterMovement()->MaxWalkSpeed = 230.f * 6.25f * G->GetStats().Speed;
		}
		if (!bBlocked) { AddMovementInput(Dir.GetSafeNormal(), 1.f); }
	}
	if (Pressed(EKeys::SpaceBar) || (bSideView && (Pressed(EKeys::W) || Pressed(EKeys::Up)))) { Jump(); }
	if (Pressed(EKeys::J) || Pressed(EKeys::LeftMouseButton)) { Attack(); }
	if (Pressed(EKeys::E)) { Interact(); }
	if (Pressed(EKeys::LeftShift) || Pressed(EKeys::RightShift)) { Dash(); }
	if (Pressed(EKeys::K)) { Whirl(); }
	if (Pressed(EKeys::F)) { Bolt(); }
}
