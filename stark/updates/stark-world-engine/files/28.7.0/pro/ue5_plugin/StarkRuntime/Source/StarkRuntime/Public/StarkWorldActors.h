// Stark World Engine Runtime - world objects: items and crystals to pick up, chests, locked doors, portals between levels,
// checkpoints, 2.5D hazards / exits, and projectiles. Each has an ArtMesh slot (Fab / Megascans swap point).
// AActor: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/GameFramework/AActor
// UStaticMeshComponent: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/Components/UStaticMeshComponent
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "StarkWorldActors.generated.h"

class UStaticMeshComponent;
class UStaticMesh;
class UBoxComponent;
class UPointLightComponent;

UENUM(BlueprintType)
enum class EStarkThing : uint8
{
	Item, Crystal, Chest, Door, Portal, Checkpoint, Hazard, Exit
};

UCLASS()
class STARKRUNTIME_API AStarkInteractable : public AActor
{
	GENERATED_BODY()
public:
	AStarkInteractable();
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") EStarkThing Kind = EStarkThing::Item;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 ObjectIndex = -1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString GoneKeyOverride;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Item;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Count = 1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Gold = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString KeyItem = TEXT("key");
	/** Portal / exit destination level (-1 = the next level). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Target = -1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString LockQuest;
	/** centimetres */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float TriggerRadius = 130.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FLinearColor Color = FLinearColor(0.4f, 1.f, 0.7f);
	/** Fab / Megascans swap slot: a static mesh shown instead of the proxy shapes. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine|Art") TObjectPtr<UStaticMesh> ArtMesh;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine|Art") float ArtScale = 1.f;

	UPROPERTY(VisibleAnywhere, Category = "Stark World Engine") TObjectPtr<USceneComponent> Root;
	UPROPERTY(VisibleAnywhere, Category = "Stark World Engine") TObjectPtr<UStaticMeshComponent> MeshA;
	UPROPERTY(VisibleAnywhere, Category = "Stark World Engine") TObjectPtr<UStaticMeshComponent> MeshB;
	UPROPERTY(VisibleAnywhere, Category = "Stark World Engine") TObjectPtr<UStaticMeshComponent> MeshC;
	UPROPERTY(VisibleAnywhere, Category = "Stark World Engine") TObjectPtr<UBoxComponent> Blocker;
	UPROPERTY(VisibleAnywhere, Category = "Stark World Engine") TObjectPtr<UPointLightComponent> Glow;

	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") bool bOpened = false;
	/** Engine basic shapes used as proxies (held here so they stay loaded). */
	UPROPERTY() TObjectPtr<UStaticMesh> ProxyCube;
	UPROPERTY() TObjectPtr<UStaticMesh> ProxySphere;
	UPROPERTY() TObjectPtr<UStaticMesh> ProxyCylinder;
	UPROPERTY() TObjectPtr<UStaticMesh> ProxyCone;

	UFUNCTION(BlueprintPure, Category = "Stark World Engine") bool CanInteract() const;
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") FString PromptText() const;
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void Interact(AActor* By);
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") int32 Destination() const;
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") bool IsLocked() const;
	/** Rebuilds the proxy shapes / tint from Kind, Color and ArtMesh (the build script calls it after setting them). */
	UFUNCTION(BlueprintCallable, CallInEditor, Category = "Stark World Engine") void RefreshVisuals();
	FString GetGoneKey() const;

	virtual void OnConstruction(const FTransform& Transform) override;
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
	virtual void Tick(float DeltaSeconds) override;

private:
	void SetupVisuals();
	void Touch();
	bool bTaken = false;
	bool bWarned = false;
	float Age = 0.f;
};

UCLASS()
class STARKRUNTIME_API AStarkProjectile : public AActor
{
	GENERATED_BODY()
public:
	AStarkProjectile();
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FVector Velocity = FVector::ZeroVector;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Damage = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") bool bFromEnemy = true;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Life = 2.4f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FLinearColor Color = FLinearColor(0.6f, 1.f, 0.4f);
	UPROPERTY(VisibleAnywhere, Category = "Stark World Engine") TObjectPtr<UStaticMeshComponent> Mesh;
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;
};
