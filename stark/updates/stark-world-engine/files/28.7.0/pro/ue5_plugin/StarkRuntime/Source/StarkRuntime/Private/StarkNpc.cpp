// Stark World Engine Runtime - NPCs (see StarkNpc.h).
// UActorComponent::TickComponent: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/Components/UActorComponent/TickComponent
// UChildActorComponent::SetChildActorClass: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/Components/UChildActorComponent/SetChildActorClass
#include "StarkNpc.h"
#include "StarkGameSubsystem.h"
#include "StarkRules.h"
#include "StarkCharacter.h"
#include "Components/CapsuleComponent.h"
#include "Components/ChildActorComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/GameInstance.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "UObject/ConstructorHelpers.h"

static UStarkGameSubsystem* StarkSubN(const UObject* Ctx)
{
	const UWorld* W = Ctx ? Ctx->GetWorld() : nullptr;
	UGameInstance* GI = W ? W->GetGameInstance() : nullptr;
	return GI ? GI->GetSubsystem<UStarkGameSubsystem>() : nullptr;
}

UStarkNpcComponent::UStarkNpcComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
}

void UStarkNpcComponent::BeginPlay()
{
	Super::BeginPlay();
	if (UStarkGameSubsystem* G = StarkSubN(this)) { G->RegisterNpc(this); }
}

void UStarkNpcComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	if (UStarkGameSubsystem* G = StarkSubN(this)) { G->UnregisterNpc(this); }
	Super::EndPlay(EndPlayReason);
}

void UStarkNpcComponent::Interact(AActor* By)
{
	UStarkGameSubsystem* G = StarkSubN(this);
	if (!G) { return; }
	if (By && GetOwner())
	{
		FVector To = By->GetActorLocation() - GetOwner()->GetActorLocation();
		To.Z = 0.f;
		if (!To.IsNearlyZero()) { GetOwner()->SetActorRotation(To.Rotation()); }
	}
	G->Talk(NpcId, DialogId, DisplayName, FallbackLine);
}

FString UStarkNpcComponent::Marker() const
{
	UStarkGameSubsystem* G = StarkSubN(this);
	if (!G || !G->Rules) { return FString(); }
	if (G->Rules->IsTalkTarget(NpcId)) { return TEXT("?"); }
	return G->Rules->OffersQuest(NpcId) ? TEXT("!") : FString();
}

void UStarkNpcComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	UStarkGameSubsystem* G = StarkSubN(this);
	AActor* Me = GetOwner();
	AStarkPlayerCharacter* Pl = G ? G->GetPlayer() : nullptr;
	if (!G || !G->Rules || !Me || !Pl || G->IsBusy()) { return; }
	FVector To = Pl->GetActorLocation() - Me->GetActorLocation();
	To.Z = 0.f;
	const float D = To.Size();
	if (D < 500.f && D > 1.f) { Me->SetActorRotation(FMath::RInterpTo(Me->GetActorRotation(), To.Rotation(), DeltaTime, 5.f)); }
	const FStarkQuestStep* Es = G->Rules->EscortStep(NpcId);
	if (!Es) { return; }
	// escort: follow the hero (teleport behind when far behind), like the browser engine
	if (D > 900.f)
	{
		Me->SetActorLocation(Pl->GetActorLocation() - Pl->FacingVector() * 180.f, false, nullptr, ETeleportType::TeleportPhysics);
	}
	else if (D > 220.f)
	{
		if (APawn* Pawn = Cast<APawn>(Me)) { Pawn->AddMovementInput(To.GetSafeNormal(), 1.f); }
		else { Me->SetActorLocation(Me->GetActorLocation() + To.GetSafeNormal() * FMath::Min(700.f * 0.95f, D * 2.5f) * DeltaTime); }
	}
	const FVector2D P = UEToStarkXZ(Me->GetActorLocation());
	const float R = Es->R > 0.f ? Es->R : 3.f;
	if (FVector2D(P.X - Es->X, P.Y - Es->Z).Size() < R)
	{
		FStarkEvent E;
		E.Npc = NpcId;
		G->Rules->Event(TEXT("escort"), E);
		if (!bSafeSaid) { bSafeSaid = true; G->Rules->Toast(DisplayName + TEXT(" is safe!"), TEXT("q")); }
		G->Changed();
	}
}

AStarkNpcCharacter::AStarkNpcCharacter()
{
	PrimaryActorTick.bCanEverTick = true;
	GetCapsuleComponent()->InitCapsuleSize(40.f, 90.f);
	GetCharacterMovement()->MaxWalkSpeed = 665.f;
	GetCharacterMovement()->GravityScale = 2400.f / 980.f;
	AutoPossessAI = EAutoPossessAI::PlacedInWorldOrSpawned;
	Npc = CreateDefaultSubobject<UStarkNpcComponent>(TEXT("StarkNpc"));
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Cone(TEXT("/Engine/BasicShapes/Cone.Cone"));
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Sphere(TEXT("/Engine/BasicShapes/Sphere.Sphere"));
	BodyMesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("BodyMesh"));
	BodyMesh->SetupAttachment(RootComponent);
	BodyMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	BodyMesh->SetRelativeLocation(FVector(0.f, 0.f, -20.f));
	BodyMesh->SetRelativeScale3D(FVector(0.9f, 0.9f, 1.4f));
	HeadMesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("HeadMesh"));
	HeadMesh->SetupAttachment(RootComponent);
	HeadMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	HeadMesh->SetRelativeLocation(FVector(0.f, 0.f, 65.f));
	HeadMesh->SetRelativeScale3D(FVector(0.5f));
	if (Cone.Succeeded()) { BodyMesh->SetStaticMesh(Cone.Object); }
	if (Sphere.Succeeded()) { HeadMesh->SetStaticMesh(Sphere.Object); }
	Visual = CreateDefaultSubobject<UChildActorComponent>(TEXT("Visual"));
	Visual->SetupAttachment(RootComponent);
	Visual->SetRelativeLocation(FVector(0.f, 0.f, -90.f));
}

void AStarkNpcCharacter::OnConstruction(const FTransform& Transform)
{
	Super::OnConstruction(Transform);
	if (VisualClass)
	{
		Visual->SetChildActorClass(VisualClass);
		BodyMesh->SetVisibility(false);
		HeadMesh->SetVisibility(false);
	}
}

void AStarkNpcCharacter::BeginPlay()
{
	Super::BeginPlay();
	if (!VisualClass)
	{
		if (UMaterialInterface* Base = BodyMesh->GetMaterial(0))
		{
			if (UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Base, this))
			{
				Mid->SetVectorParameterValue(TEXT("Color"), Color);
				BodyMesh->SetMaterial(0, Mid);
			}
		}
	}
}
